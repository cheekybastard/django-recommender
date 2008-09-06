from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User

from voting.models import Vote

from os.path import abspath, dirname, join
import sys
from site import addsitedir

path = addsitedir(abspath(join(dirname(__file__), 'recommender/site-packages')), set())
if path: sys.path = list(path) + sys.path

import statistics

class RecommenderManager(models.Manager):

    MIN_RECOMMENDATION_VALUE = 0
    MIN_SIMILARITY_VALUE = 0.25
    
    def get_best_items_for_user(self, user, user_list, item_list):
        user_item_matrix = self.create_matrix(user_list, item_list)

        recs = self._get_usb_recommendations(user.id, user_item_matrix)
        recs.sort(reverse=True)
        
        ctype = ContentType.objects.get_for_model(item_list[0])
        items = [(value,ctype.get_object_for_this_type(id = rec)) for value,rec in recs if value>self.MIN_RECOMMENDATION_VALUE]
        return items
        
    def get_similar_users(self, user, user_list, item_list):
        user_item_matrix = self.create_matrix(user_list, item_list)
        sim_list = []
        for other in user_list:
            if user==other:continue
            sim=self._distance_matrix_p1_p2(user_item_matrix,user.id,other.id) #returns a 0..1 value
            if sim>self.MIN_SIMILARITY_VALUE:
                sim_list.append((sim,other))
            
        sim_list.sort(reverse=True)
        return sim_list

    def get_best_users_for_item(self, item, user_list, item_list):
        user_item_matrix = self.create_matrix(user_list, item_list)
        item_user_matrix = self.rotate_matrix(user_item_matrix)

        recs = self._get_usb_recommendations(item.id, item_user_matrix)
        recs.sort(reverse=True)

        users = [(value,User.objects.get(id = rec)) for value,rec in recs if value>self.MIN_RECOMMENDATION_VALUE]
        
        return users
    
    def get_similar_items(self, item, user_list, item_list):
        user_item_matrix = self.create_matrix(user_list, item_list)
        item_user_matrix = self.rotate_matrix(user_item_matrix)
        sim_list = []
        for other in item_list:
            if item==other:continue
            sim=self._distance_matrix_p1_p2(item_user_matrix,item.id,other.id) #returns a 0..1 value
            if sim>self.MIN_SIMILARITY_VALUE:
                sim_list.append((sim,other))
            
        sim_list.sort(reverse=True)
        return sim_list
        
    def create_matrix(self, users, items):
        user_item_matrix = {}
        for user in users:
            votes_for_user = Vote.objects.get_for_user_in_bulk(items, user)
            user_item_matrix[user.id] = votes_for_user
        
        return user_item_matrix
    
    def rotate_matrix(self, matrix):
        rotated_matrix = {}
        for user in matrix:
            for item in matrix[user]:
              rotated_matrix.setdefault(item,{})
              rotated_matrix[item][user]=matrix[user][item]
        return rotated_matrix
        
    #Return [0..1] where -1 is not correlated, and 1 is fully correlated
    def _pearson_correlation(self,v1,v2):
        '''>>> eng=RecommenderManager()
           >>> v1=[0,10,10,0,10]
           >>> v2=[10,0,0,10,0]
           >>> eng._pearson_correlation(v1,v2)
           0.0
           >>> v2=v1
           >>> eng._pearson_correlation(v1,v2)
           1.0
           >>> v2=[0,10,0,10,0]
           >>> eng._pearson_correlation(v1,v2)
           0.41666666666666669
        '''
        try:
            c= statistics.correlation(v1,v2)        
        except statistics.error:
            c= -1
        
        return (c+1.0)/2.0

    def _distance_matrix_p1_p2(self, prefs, p1, p2):
        ''' >>> eng=RecommenderManager()
            >>> prefs={}
            >>> prefs['p1']={'item1': 0, 'item2': 0, 'item3': 10, 'item4': 10, 'item5':0}
            >>> prefs['p2']={'item1': 10, 'item2': 10, 'item3': 0, 'item4': 0, 'item5':10}
            >>> prefs['p3']={'item1': 0, 'item2': 10, 'item3': 0, 'item4': 0, 'item5':10}
            >>> prefs['p4']={'item1': 0, 'item2': 0, 'item3': 0, 'item4': 0, 'item5':10}
            >>> eng._distance_matrix_p1_p2(prefs,'p1','p1')
            1.0
            >>> eng._distance_matrix_p1_p2(prefs,'p1','p2')
            0.0
            >>> eng._distance_matrix_p1_p2(prefs,'p1','p3')
            0.16666666666666669
            >>> eng._distance_matrix_p1_p2(prefs,'p1','p4')
            0.29587585476806849
            >>> eng._distance_matrix_p1_p2(prefs,'p2','p4')
            0.70412414523193156
            >>> eng._distance_matrix_p1_p2(prefs,'p2','p3')
            0.83333333333333326
        '''        
        v1=[]
        v2=[]
        for item in prefs[p1]:
            if item in prefs[p2]:
                v1.append(prefs[p1][item].vote)
                v2.append(prefs[p2][item].vote)
            
        # if they have no ratings in common, return 0
        if len(v1)==0: return -1
      
        return self._pearson_correlation(v1,v2)
        
    
#####User Based Recommendation methods
    
    def _get_usb_recommendations(self, element, matrix):
        ''' Calculates recommendations for a given element by using an average of every other element's rankings.
            Returns a pair (value,element_id), where value is [0..X] where 0 doesn't match, and X fully matches
            >>> eng=RecommenderManager()
            >>> matrix={}
            >>> matrix['user1']={'item1':-1, 'item3': 1, 'item4': 1, 'item5':0}
            >>> matrix['user2']={'item1': 1, 'item2': 1, 'item3':-1, 'item4':-1, 'item5':10,'item6':10}
            >>> matrix['user3']={'item1':-1, 'item2': 1, 'item4':-1, 'item5':10,'item6':10,'item7':-1}
            >>> matrix['user4']={'item1':-1, 'item2':-1, 'item3':-1, 'item4':-1, 'item5':10,'item7':10,'item8':10}
        '''
        totals={}
        simSums={}
        for other in matrix:
            # don't compare me to myself
            if other==element: continue
            sim=self._distance_matrix_p1_p2(matrix,element,other)
            # ignore scores of zero or lower
            if sim<=0: continue
            for item in matrix[other]:
                # only score events I haven't seen yet
                if item not in matrix[element]:
                    # Similarity * Score
                    totals.setdefault(item,0)
                    totals[item]+=matrix[other][item].vote*sim
                    # Sum of similarities
                    simSums.setdefault(item,0)
#                    simSums[item]+=sim #book
                    simSums[item]+=1 # my version !!
        # Create the normalized list...?
        rankings=[(total/simSums[item],item) for item,total in totals.items( )]
        return rankings
    
    